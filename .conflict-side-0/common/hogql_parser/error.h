#pragma once

#include <stdexcept>
#include <string>

#define ERROR_CLASS_DEFINITION(NAME, BASE)                               \
  class NAME : public BASE {                                             \
   public:                                                               \
    size_t start;                                                        \
    size_t end;                                                          \
    explicit NAME(const std::string& message, size_t start, size_t end); \
    explicit NAME(const char* message, size_t start, size_t end);        \
    explicit NAME(const std::string& message);                           \
    explicit NAME(const char* message);                                  \
  };

ERROR_CLASS_DEFINITION(HogQLError, std::runtime_error)

// The input does not conform to HogQL syntax.
ERROR_CLASS_DEFINITION(SyntaxError, HogQLError)

// This feature isn't implemented in HogQL (yet).
ERROR_CLASS_DEFINITION(NotImplementedError, HogQLError)

// An internal problem in the parser layer.
ERROR_CLASS_DEFINITION(ParsingError, HogQLError)

// Python runtime errored out somewhere - this means we must use the error it's already raised.
class PyInternalError : public std::exception {
 public:
  PyInternalError();
};
