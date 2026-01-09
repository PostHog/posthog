#define PY_SSIZE_T_CLEAN
#include <Python.h>

// MODULE STATE

// Module state for storing reference to Python errors module (needed for exception handling)
typedef struct {
  PyObject* errors_module;
} parser_state;