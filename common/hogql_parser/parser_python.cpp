// parser_python.cpp - Python C Extension Bindings for HogQL Parser
// This file provides Python bindings for the core parser (parser_core.cpp).

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <boost/algorithm/string.hpp>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "json_builder.h"
#include "parser_python.h"
#include "string.h"

using namespace std;

// Include the core parser implementation
#include "parser_core.cpp"

// PYTHON-SPECIFIC ERROR HANDLING

#define HANDLE_HOGQL_ERROR(TYPE, OTHER_CLEANUP)                                                         \
  (const TYPE& e) {                                                                                     \
    string err_what = e.what();                                                                         \
    PyObject *error_type = NULL, *py_err_args = NULL, *py_err = NULL, *py_start = NULL, *py_end = NULL; \
    int err_indicator = 0;                                                                              \
    error_type = PyObject_GetAttrString(state->errors_module, #TYPE);                                   \
    if (!error_type) goto exit##TYPE;                                                                   \
    py_err_args = Py_BuildValue("(s#)", err_what.data(), err_what.size());                              \
    if (!py_err_args) goto exit##TYPE;                                                                  \
    py_err = PyObject_CallObject(error_type, py_err_args);                                              \
    if (!py_err) goto exit##TYPE;                                                                       \
    py_start = Py_BuildValue("i", e.start);                                                             \
    if (!py_start) goto exit##TYPE;                                                                     \
    py_end = Py_BuildValue("i", e.end);                                                                 \
    if (!py_end) goto exit##TYPE;                                                                       \
    err_indicator = PyObject_SetAttrString(py_err, "start", py_start);                                  \
    if (err_indicator == -1) goto exit##TYPE;                                                           \
    err_indicator = PyObject_SetAttrString(py_err, "end", py_end);                                      \
    if (err_indicator == -1) goto exit##TYPE;                                                           \
    PyErr_SetObject(error_type, py_err);                                                                \
    exit##TYPE : Py_XDECREF(py_end);                                                                    \
    Py_XDECREF(py_start);                                                                               \
    Py_XDECREF(py_err);                                                                                 \
    Py_XDECREF(error_type);                                                                             \
    Py_XDECREF(py_err_args);                                                                            \
    OTHER_CLEANUP                                                                                       \
    return NULL;                                                                                        \
  }

// MODULE STATE HELPERS

parser_state* get_module_state(PyObject* module) {
  return (parser_state*)PyModule_GetState(module);
}

class HogQLErrorListener : public antlr4::BaseErrorListener {
 public:
  string input;

  HogQLErrorListener(string input) : input(input) {}

  void syntaxError(
      antlr4::Recognizer* recognizer,
      antlr4::Token* offendingSymbol,
      size_t line,
      size_t charPositionInLine,
      const string& msg,
      exception_ptr e
  ) override {
    size_t start = getPosition(line, charPositionInLine);
    if (start == string::npos) {
      start = 0;
    }
    throw SyntaxError(msg, start, input.size());
  }

 private:
  size_t getPosition(size_t line, size_t column) {
    size_t linePosition = 0;
    for (size_t i = 0; i < line - 1; i++) {
      size_t endOfLine = input.find("\n", linePosition);
      if (endOfLine == string::npos) {
        return string::npos;
      }
      linePosition = endOfLine + 1;
    }
    return linePosition + column;
  }
};

// MODULE METHODS

#define METHOD_PARSE_NODE(PASCAL_CASE, CAMEL_CASE, SNAKE_CASE)                                               \
  static PyObject* method_parse_##SNAKE_CASE(PyObject* self, PyObject* args, PyObject* kwargs) {             \
    parser_state* state = get_module_state(self);                                                            \
    const char* str;                                                                                         \
    int internal = 0;                                                                                        \
    static const char* kwlist[] = {"input", "is_internal", NULL};                                            \
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|p", (char**)kwlist, &str, &internal)) {                \
      return NULL;                                                                                           \
    }                                                                                                        \
    auto input_stream = new antlr4::ANTLRInputStream(str, strnlen(str, 65536));                              \
    auto lexer = new HogQLLexer(input_stream);                                                               \
    auto stream = new antlr4::CommonTokenStream(lexer);                                                      \
    auto parser = new HogQLParser(stream);                                                                   \
    parser->removeErrorListeners();                                                                          \
    auto error_listener = new HogQLErrorListener(str);                                                       \
    parser->addErrorListener(error_listener);                                                                \
    HogQLParser::PASCAL_CASE##Context* parse_tree;                                                           \
    try {                                                                                                    \
      parse_tree = parser->CAMEL_CASE();                                                                     \
    } catch HANDLE_HOGQL_ERROR(                                                                              \
        SyntaxError, delete error_listener; delete parser; delete stream; delete lexer; delete input_stream; \
    ) catch (const antlr4::EmptyStackException& e) {                                                         \
      delete error_listener;                                                                                 \
      delete parser;                                                                                         \
      delete stream;                                                                                         \
      delete lexer;                                                                                          \
      delete input_stream;                                                                                   \
      PyObject* error_type = PyObject_GetAttrString(state->errors_module, "SyntaxError");                    \
      if (error_type) {                                                                                      \
        PyErr_SetString(error_type, "Unmatched curly bracket");                                              \
      }                                                                                                      \
      return NULL;                                                                                           \
    } catch (...) {                                                                                          \
      delete error_listener;                                                                                 \
      delete parser;                                                                                         \
      delete stream;                                                                                         \
      delete lexer;                                                                                          \
      delete input_stream;                                                                                   \
      PyObject* error_type = PyObject_GetAttrString(state->errors_module, "ParsingError");                   \
      if (error_type) {                                                                                      \
        PyErr_SetString(error_type, "Unexpected Antlr exception in C++ parser");                             \
      }                                                                                                      \
      return NULL;                                                                                           \
    };                                                                                                       \
    HogQLParseTreeConverter converter = HogQLParseTreeConverter(internal == 1);                              \
    string result_json = converter.visitAsJSONFinal(parse_tree);                                             \
    delete error_listener;                                                                                   \
    delete parser;                                                                                           \
    delete stream;                                                                                           \
    delete lexer;                                                                                            \
    delete input_stream;                                                                                     \
    return PyUnicode_FromStringAndSize(result_json.data(), result_json.size());                              \
  }

METHOD_PARSE_NODE(Expr, expr, expr)
METHOD_PARSE_NODE(OrderExpr, orderExpr, order_expr)
METHOD_PARSE_NODE(Select, select, select)
METHOD_PARSE_NODE(FullTemplateString, fullTemplateString, full_template_string)
METHOD_PARSE_NODE(Program, program, program)

#undef METHOD_PARSE_NODE

static PyObject* method_parse_string_literal_text(PyObject* self, PyObject* args) {
  parser_state* state = get_module_state(self);
  const char* str;
  if (!PyArg_ParseTuple(args, "s", &str)) {
    return NULL;
  }
  string unquoted_string;
  try {
    unquoted_string = parse_string_literal_text(str);
  } catch HANDLE_HOGQL_ERROR(SyntaxError, );
  return PyUnicode_FromStringAndSize(unquoted_string.data(), unquoted_string.size());
}

// MODULE SETUP

static PyMethodDef parser_methods[] = {
    {.ml_name = "parse_expr",
     .ml_meth = (PyCFunction)method_parse_expr,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL expression string into an AST"},
    {.ml_name = "parse_order_expr",
     .ml_meth = (PyCFunction)method_parse_order_expr,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the ORDER BY clause string into an AST"},
    {.ml_name = "parse_select",
     .ml_meth = (PyCFunction)method_parse_select,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL SELECT statement string into an AST"},
    {.ml_name = "parse_full_template_string",
     .ml_meth = (PyCFunction)method_parse_full_template_string,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse a Hog template string into an AST"},
    {.ml_name = "parse_program",
     .ml_meth = (PyCFunction)method_parse_program,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse a Hog program into an AST"},
    {.ml_name = "parse_string_literal_text",
     .ml_meth = method_parse_string_literal_text,
     .ml_flags = METH_VARARGS,
     .ml_doc = "Unquote the string (an identifier or a string literal))"},
    {NULL, NULL, 0, NULL}
};

static int parser_modexec(PyObject* module) {
  parser_state* state = get_module_state(module);
  state->errors_module = PyImport_ImportModule("posthog.hogql.errors");
  if (!state->errors_module) {
    return -1;
  }
  return 0;
}

static PyModuleDef_Slot parser_slots[] = {
    {Py_mod_exec, (void*)parser_modexec},  // If Python were written in C++, then Py_mod_exec would be typed better, but
                                           // because it's in C, it expects a void pointer
    {0, NULL}
};

static int parser_traverse(PyObject* module, visitproc visit, void* arg) {
  parser_state* state = get_module_state(module);
  Py_VISIT(state->errors_module);
  return 0;
}

static int parser_clear(PyObject* module) {
  parser_state* state = get_module_state(module);
  Py_CLEAR(state->errors_module);
  return 0;
}

static struct PyModuleDef parser = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "hogql_parser",
    .m_doc = "HogQL parsing",
    .m_size = sizeof(parser_state),
    .m_methods = parser_methods,
    .m_slots = parser_slots,
    .m_traverse = parser_traverse,
    .m_clear = parser_clear,
};

PyMODINIT_FUNC PyInit_hogql_parser(void) {
  return PyModuleDef_Init(&parser);
}