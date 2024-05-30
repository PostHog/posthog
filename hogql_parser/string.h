#pragma once

#include <string>

#include "antlr4-runtime.h"

std::string replace_common_escape_characters(std::string text);

std::string parse_string_literal_text(std::string text);

std::string parse_string_literal_ctx(antlr4::tree::TerminalNode* node);

std::string parse_string_text_ctx(antlr4::tree::TerminalNode* node, bool escape_quotes);
