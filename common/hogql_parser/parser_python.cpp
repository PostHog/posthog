#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "parser_python.h"
#include "string.h"

#define VISIT(RULE) any visit##RULE(HogQLParser::RULE##Context* ctx) override
#define VISIT_UNSUPPORTED(RULE)                            \
  VISIT(RULE) {                                            \
    throw NotImplementedError("Unsupported rule: " #RULE); \
  }

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
    py_start = PyLong_FromSize_t(e.start);                                                              \
    if (!py_start) goto exit##TYPE;                                                                     \
    py_end = PyLong_FromSize_t(e.end);                                                                  \
    if (!py_end) goto exit##TYPE;                                                                       \
    err_indicator = PyObject_SetAttrString(py_err, "start", py_start);                                  \
    if (err_indicator == -1) goto exit##TYPE;                                                           \
    err_indicator = PyObject_SetAttrString(py_err, "end", py_end);                                      \
    if (err_indicator == -1) goto exit##TYPE;                                                           \
    PyErr_SetObject(error_type, py_err);                                                                \
    exit##TYPE :;                                                                                       \
    Py_XDECREF(py_end);                                                                                 \
    Py_XDECREF(py_start);                                                                               \
    Py_XDECREF(py_err);                                                                                 \
    Py_XDECREF(error_type);                                                                             \
    OTHER_CLEANUP                                                                                       \
    return NULL;                                                                                        \
  }

#define RETURN_NEW_AST_NODE(TYPE_NAME, KWARGS_FORMAT, ...)                                                    \
  PyObject* ret = build_ast_node(TYPE_NAME, KWARGS_FORMAT, __VA_ARGS__);                                      \
  /* Fortunately we don't need to care about decrementing Py_BuildValue/Py_VaBuildValue args, */              \
  /* so just throw is enough: https://github.com/python/cpython/blob/a254120f/Python/modsupport.c#L147-L148*/ \
  if (!ret) throw PyInternalError();                                                                          \
  return ret

using namespace std;

// PYTHON UTILS (`X_` stands for "extension")

// Extend `list` with `extension` in-place. Return 0 on success, -1 on error.
int X_PyList_Extend(PyObject* list, PyObject* extension) {
  Py_ssize_t list_size = PyList_Size(list);
  if (list_size == -1) {
    return -1;
  }
  Py_ssize_t extension_size = PyList_Size(extension);
  if (extension_size == -1) {
    return -1;
  }
  return PyList_SetSlice(list, list_size, list_size + extension_size, extension);
}

// Decref all elements of a vector.
void X_Py_DECREF_ALL(vector<PyObject*> objects) {
  for (PyObject* object : objects) {
    Py_DECREF(object);
  }
}

// Construct a Python list from a vector of strings. Return value: New reference (or NULL on error).
PyObject* X_PyList_FromStrings(const vector<string>& items) {
  PyObject* list = PyList_New(items.size());
  if (!list) {
    return NULL;
  }
  for (size_t i = 0; i < items.size(); i++) {
    PyObject* value = PyUnicode_FromStringAndSize(items[i].data(), items[i].size());
    if (!value) {
      Py_DECREF(list);
      return NULL;
    }
    PyList_SET_ITEM(list, i, value);
  }
  return list;
}

// PARSING AND AST CONVERSION

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

// MODULE STATE

parser_state* get_module_state(PyObject* module) {
  return static_cast<parser_state*>(PyModule_GetState(module));
}

// Include JSON parser methods (depends on get_module_state and HogQLErrorListener)

#include "parser_json_python.cpp"
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


// MODULE METHODS

static PyMethodDef parser_methods[] = {
    {.ml_name = "parse_string_literal_text",
     .ml_meth = method_parse_string_literal_text,
     .ml_flags = METH_VARARGS,
     .ml_doc = "Unquote the string (an identifier or a string literal))"},

    // JSON output methods
    {.ml_name = "parse_expr_json",
     .ml_meth = (PyCFunction)method_parse_expr_json,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL expression string into a JSON AST"},
    {.ml_name = "parse_order_expr_json",
     .ml_meth = (PyCFunction)method_parse_order_expr_json,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the ORDER BY clause string into a JSON AST"},
    {.ml_name = "parse_select_json",
     .ml_meth = (PyCFunction)method_parse_select_json,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL SELECT statement string into a JSON AST"},
    {.ml_name = "parse_full_template_string_json",
     .ml_meth = (PyCFunction)method_parse_full_template_string_json,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse a Hog template string into a JSON AST"},
    {.ml_name = "parse_program_json",
     .ml_meth = (PyCFunction)method_parse_program_json,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse a Hog program into a JSON AST"},

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
