#include "error.h"

using namespace std;

HogQLSyntaxError::HogQLSyntaxError(const string& message) : runtime_error(message) {}
HogQLSyntaxError::HogQLSyntaxError(const char* message) : runtime_error(message) {}

HogQLNotImplementedError::HogQLNotImplementedError(const string& message) : logic_error(message) {}
HogQLNotImplementedError::HogQLNotImplementedError(const char* message) : logic_error(message) {}

HogQLParsingError::HogQLParsingError(const string& message) : logic_error(message) {}
HogQLParsingError::HogQLParsingError(const char* message) : logic_error(message) {}
