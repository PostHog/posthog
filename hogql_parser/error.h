#pragma once

#include <stdexcept>
#include <string>

#define EXCEPTION_CLASS_DEFINITION(NAME, BASE)                           \
  class NAME : public BASE {                                             \
   public:                                                               \
    size_t start;                                                        \
    size_t end;                                                          \
    explicit NAME(const std::string& message, size_t start, size_t end); \
    explicit NAME(const char* message, size_t start, size_t end);        \
    explicit NAME(const std::string& message);                           \
    explicit NAME(const char* message);                                  \
  };

EXCEPTION_CLASS_DEFINITION(HogQLException, std::runtime_error)

// The input does not conform to HogQL syntax.
EXCEPTION_CLASS_DEFINITION(SyntaxException, HogQLException)

// This feature isn't implemented in HogQL (yet).
EXCEPTION_CLASS_DEFINITION(NotImplementedException, HogQLException)

// An internal problem in the parser layer.
EXCEPTION_CLASS_DEFINITION(ParsingException, HogQLException)

// Python runtime errored out somewhere - this means we must use the error it's already raised.
class PyInternalException : public std::exception {
 public:
  PyInternalException();
};
