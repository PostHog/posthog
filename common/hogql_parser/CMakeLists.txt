# CMakeLists.txt - Build configuration for HogQL Parser WebAssembly

cmake_minimum_required(VERSION 3.10)
project(hogql_parser_wasm)

# Set C++ standard
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Emscripten-specific settings
if(EMSCRIPTEN)
    set(CMAKE_EXECUTABLE_SUFFIX ".js")

    # Emscripten compiler flags
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s WASM=1")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s MODULARIZE=1")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s EXPORT_NAME='createHogQLParser'")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s ALLOW_MEMORY_GROWTH=1")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s EXPORTED_RUNTIME_METHODS=['ccall','cwrap']")
    # Removed -s EXPORT_ES6=1 to generate CommonJS output for Jest compatibility
    # Use SINGLE_FILE to embed WASM in the JS file for easier distribution
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s SINGLE_FILE=1")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} --bind")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fexceptions")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s DISABLE_EXCEPTION_CATCHING=0")

    # Optimization flags (for production build)
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -O3")
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -s ASSERTIONS=0")

    # Debug flags (for development)
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -g")
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -s ASSERTIONS=1")
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -s SAFE_HEAP=1")
endif()

# Find ANTLR4 runtime
# Note: You may need to adjust these paths for your ANTLR4 installation
if(EMSCRIPTEN)
    # For Emscripten, use WASM-compiled ANTLR4 runtime
    set(ANTLR4_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/antlr4_wasm/runtime/Cpp/runtime/src" CACHE PATH "ANTLR4 include directory")
    set(ANTLR4_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/antlr4_wasm/build_wasm/runtime" CACHE PATH "ANTLR4 library directory")
    set(BOOST_INCLUDE_DIR "/opt/homebrew/include" CACHE PATH "Boost include directory")
else()
    find_path(ANTLR4_INCLUDE_DIR antlr4-runtime/antlr4-runtime.h)
    find_library(ANTLR4_LIBRARY antlr4-runtime)
    find_package(Boost REQUIRED)
    set(BOOST_INCLUDE_DIR ${Boost_INCLUDE_DIRS})
endif()

include_directories(${ANTLR4_INCLUDE_DIR})
include_directories(${BOOST_INCLUDE_DIR})

# Source files
set(PARSER_SOURCES
    HogQLLexer.cpp
    HogQLParser.cpp
    HogQLParserBaseVisitor.cpp
    HogQLParserVisitor.cpp
    error.cpp
    string.cpp
    json_builder.cpp
    parser_wasm.cpp
)

# Create the WASM executable
add_executable(hogql_parser ${PARSER_SOURCES})

# Link ANTLR4 runtime
if(NOT EMSCRIPTEN)
    target_link_libraries(hogql_parser ${ANTLR4_LIBRARY})
else()
    # For Emscripten, link statically
    target_link_libraries(hogql_parser ${ANTLR4_LIB_DIR}/libantlr4-runtime.a)
endif()

# Installation
install(TARGETS hogql_parser
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION lib
)

# Install WASM output files
if(EMSCRIPTEN)
    # With SINGLE_FILE=1, the WASM is embedded in the JS file
    # Only need to install the JS file
    install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/hogql_parser.js
        DESTINATION dist
    )
endif()
