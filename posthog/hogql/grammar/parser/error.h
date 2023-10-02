#pragma once

#include <stdexcept>
#include <string>

// The input does not conform to HogQL syntax.
class HogQLSyntaxError : public std::runtime_error {
 public:
  explicit HogQLSyntaxError(const std::string& message);
  explicit HogQLSyntaxError(const char* message);
};

// This feature isn't implemented in HogQL (yet).
class HogQLNotImplementedError : public std::logic_error {
 public:
  explicit HogQLNotImplementedError(const std::string& message);
  explicit HogQLNotImplementedError(const char* message);
};

// An internal problem in the parser layer.
class HogQLParsingError : public std::logic_error {
 public:
  explicit HogQLParsingError(const std::string& message);
  explicit HogQLParsingError(const char* message);
};
