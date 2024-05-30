#pragma once

#include <string>

#include "antlr4-runtime.h"

std::string unescape_string(std::string text);

std::string unquote_string(std::string text);

std::string unquote_string_terminal(antlr4::tree::TerminalNode* node);

std::string unquote_string_chunk_terminal(antlr4::tree::TerminalNode* node, bool escape_quotes);
