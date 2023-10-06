#include "error.h"

using namespace std;

#define EXCEPTION_CLASS_IMPLEMENTATION(NAME, BASE)                                                       \
  NAME::NAME(const string& message, size_t start, size_t end) : BASE(message), start(start), end(end) {} \
  NAME::NAME(const char* message, size_t start, size_t end) : BASE(message), start(start), end(end) {}   \
  NAME::NAME(const string& message) : BASE(message) {}                                                   \
  NAME::NAME(const char* message) : BASE(message) {}

EXCEPTION_CLASS_IMPLEMENTATION(HogQLException, runtime_error)

EXCEPTION_CLASS_IMPLEMENTATION(HogQLSyntaxException, HogQLException)
EXCEPTION_CLASS_IMPLEMENTATION(HogQLNotImplementedException, HogQLException)
EXCEPTION_CLASS_IMPLEMENTATION(HogQLParsingException, HogQLException)
