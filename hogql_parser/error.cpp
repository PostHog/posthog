#include "error.h"

using namespace std;

HogQLSyntaxError::HogQLSyntaxError(const string& message, size_t start, size_t end)
    : runtime_error(message), start(start), end(end) {}
HogQLSyntaxError::HogQLSyntaxError(const char* message, size_t start, size_t end)
    : runtime_error(message), start(start), end(end) {}

HogQLNotImplementedError::HogQLNotImplementedError(const string& message) : logic_error(message) {}
HogQLNotImplementedError::HogQLNotImplementedError(const char* message) : logic_error(message) {}

HogQLParsingError::HogQLParsingError(const string& message) : logic_error(message) {}
HogQLParsingError::HogQLParsingError(const char* message) : logic_error(message) {}
