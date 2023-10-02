#include <stdexcept>

// The input does not conform to HogQL syntax.
class HogQLSyntaxError : public std::runtime_error {
 public:
  HogQLSyntaxError(const std::string& message);
  HogQLSyntaxError(const char* message);
};

// This feature isn't implemented in HogQL (yet).
class HogQLNotImplementedError : public std::logic_error {
 public:
  HogQLNotImplementedError(const std::string& message);
  HogQLNotImplementedError(const char* message);
};

// An internal problem in the parser layer.
class HogQLParsingError : public std::logic_error {
 public:
  HogQLParsingError(const std::string& message);
  HogQLParsingError(const char* message);
};
