// parser_json_python.cpp - JSON output methods for HogQL Parser Python bindings
// This file is included by parser_python.cpp to add JSON-returning parse methods.

#include "json.h"

// Include the core JSON parser implementation
#include "parser_json.cpp"

// JSON MODULE METHODS

#define METHOD_PARSE_NODE_JSON(PASCAL_CASE, CAMEL_CASE, SNAKE_CASE)                                          \
  static PyObject* method_parse_##SNAKE_CASE##_json(PyObject* self, PyObject* args, PyObject* kwargs) {      \
    parser_state* state = get_module_state(self);                                                            \
    PyObject* str_obj;                                                                                       \
    int internal = 0;                                                                                        \
    static const char* kwlist[] = {"input", "is_internal", NULL};                                            \
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|p", (char**)kwlist, &str_obj, &internal)) {            \
      return NULL;                                                                                           \
    }                                                                                                        \
    Py_ssize_t str_len;                                                                                      \
    const char* str = PyUnicode_AsUTF8AndSize(str_obj, &str_len);                                           \
    if (!str) return NULL;                                                                                   \
    auto input_stream = new antlr4::ANTLRInputStream(str, (size_t)str_len);                                  \
    auto lexer = new HogQLLexer(input_stream);                                                               \
    auto stream = new antlr4::CommonTokenStream(lexer);                                                      \
    auto parser = new HogQLParser(stream);                                                                   \
    parser->removeErrorListeners();                                                                          \
    auto error_listener = new HogQLErrorListener(string(str, (size_t)str_len));                              \
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
    HogQLParseTreeJSONConverter json_converter = HogQLParseTreeJSONConverter(internal == 1);                 \
    string result_json = json_converter.visitAsJSONFinal(parse_tree);                                        \
    delete error_listener;                                                                                   \
    delete parser;                                                                                           \
    delete stream;                                                                                           \
    delete lexer;                                                                                            \
    delete input_stream;                                                                                     \
    return PyUnicode_FromStringAndSize(result_json.data(), result_json.size());                              \
  }

METHOD_PARSE_NODE_JSON(Expr, expr, expr)
METHOD_PARSE_NODE_JSON(OrderExpr, orderExpr, order_expr)
METHOD_PARSE_NODE_JSON(Select, select, select)
METHOD_PARSE_NODE_JSON(FullTemplateString, fullTemplateString, full_template_string)
METHOD_PARSE_NODE_JSON(Program, program, program)

#undef METHOD_PARSE_NODE_JSON
