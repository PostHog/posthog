#define PY_SSIZE_T_CLEAN
#include <Python.h>

// MODULE STATE

// Module state, primarily for storing references to Python objects used throughout the parser (such as imports)
typedef struct {
  PyObject* ast_module;
  PyObject* base_module;
  PyObject* errors_module;
} parser_state;
