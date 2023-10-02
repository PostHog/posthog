#include <stdexcept>

using namespace std;

// The input does not conform to HogQL syntax.
class HogQLSyntaxError : public runtime_error {
 public:
  explicit HogQLSyntaxError(const string& message) : runtime_error(message) {}
  explicit HogQLSyntaxError(const char* message) : runtime_error(message) {}
};

// This feature isn't implemented in HogQL (yet).
class HogQLNotImplementedError : public logic_error {
 public:
  explicit HogQLNotImplementedError(const string& message) : logic_error(message) {}
  explicit HogQLNotImplementedError(const char* message) : logic_error(message) {}
};

// An internal problem in the parser layer.
class HogQLParsingError : public logic_error {
 public:
  explicit HogQLParsingError(const string& message) : logic_error(message) {}
  explicit HogQLParsingError(const char* message) : logic_error(message) {}
};
