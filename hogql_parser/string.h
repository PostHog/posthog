#pragma once

#include <string>

#include "antlr4-runtime.h"

std::string parse_string(std::string text);

std::string parse_string_literal(antlr4::tree::TerminalNode* node);
