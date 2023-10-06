#pragma once

#include <stdexcept>
#include <string>

#define EXCEPTION_CLASS_DEFINITION(NAME, BASE, MEMBERS)                  \
  class NAME : public BASE {                                             \
   public:                                                               \
    MEMBERS                                                              \
    explicit NAME(const std::string& message, size_t start, size_t end); \
    explicit NAME(const char* message, size_t start, size_t end);        \
    explicit NAME(const std::string& message);                           \
    explicit NAME(const char* message);                                  \
  };

EXCEPTION_CLASS_DEFINITION(HogQLException, std::runtime_error, size_t start; size_t end;)

// The input does not conform to HogQL syntax.
EXCEPTION_CLASS_DEFINITION(HogQLSyntaxException, HogQLException, ;)  // The `;` means there are no extra members

// This feature isn't implemented in HogQL (yet).
EXCEPTION_CLASS_DEFINITION(HogQLNotImplementedException, HogQLException, ;)

// An internal problem in the parser layer.
EXCEPTION_CLASS_DEFINITION(HogQLParsingException, HogQLException, ;)
