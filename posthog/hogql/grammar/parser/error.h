#pragma once

#include <stdexcept>
#include <string>

// The input does not conform to HogQL syntax.
class HogQLSyntaxError : public std::runtime_error {
 public:
  size_t start;
  size_t end;

  explicit HogQLSyntaxError(const std::string& message, size_t start, size_t end);
  explicit HogQLSyntaxError(const char* message, size_t start, size_t end);
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
