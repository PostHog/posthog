#include "error.h"

using namespace std;

#define EXCEPTION_CLASS_IMPLEMENTATION(NAME, BASE)                                                       \
  NAME::NAME(const string& message, size_t start, size_t end) : BASE(message), start(start), end(end) {} \
  NAME::NAME(const char* message, size_t start, size_t end) : BASE(message), start(start), end(end) {}   \
  NAME::NAME(const string& message) : BASE(message), start(0), end(0) {}                                 \
  NAME::NAME(const char* message) : BASE(message), start(0), end(0) {}

EXCEPTION_CLASS_IMPLEMENTATION(HogQLException, runtime_error)

EXCEPTION_CLASS_IMPLEMENTATION(SyntaxException, HogQLException)
EXCEPTION_CLASS_IMPLEMENTATION(NotImplementedException, HogQLException)
EXCEPTION_CLASS_IMPLEMENTATION(ParsingException, HogQLException)

PyInternalException::PyInternalException() : exception() {}
