cmake_minimum_required(VERSION 3.10)
project(hogql_parser LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

FetchContent_Declare(
    antlr4
    GIT_REPOSITORY https://github.com/antlr/antlr4.git
    GIT_TAG 4.13.2
)

FetchContent_Declare(
    boost
    URL https://github.com/boostorg/boost/releases/download/boost-1.90.0/boost-1.90.0-b2-nodocs.7z
    URL_HASH SHA256=06df6fada5ac5eaf7d3b0579637d4f6d82ae979ba7cc7fe126efcf73140857e5
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

set(ANTLR_BUILD_CPP_TESTS OFF CACHE BOOL "" FORCE)
set(ANTLR_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(ANTLR4_WITH_STATIC_CRT OFF CACHE BOOL "" FORCE)

# Using FetchContent_Populate instead of FetchContent_MakeAvailable:
# - Boost: Header-only usage, skip slow CMake configuration
# - ANTLR4: Only need runtime/Cpp subdirectory, not the full project
FetchContent_Populate(antlr4)
FetchContent_Populate(boost)

add_subdirectory(${antlr4_SOURCE_DIR}/runtime/Cpp EXCLUDE_FROM_ALL)

# boost/algorithm/string.hpp requires multiple Boost libraries
set(BOOST_INCLUDE_DIR ${boost_SOURCE_DIR})
set(ANTLR_INCLUDE_DIR ${antlr4_SOURCE_DIR}/runtime/Cpp/runtime/src/)

set(PARSER_SOURCES
    HogQLLexer.cpp
    HogQLParser.cpp
    HogQLParserBaseVisitor.cpp
    HogQLParserVisitor.cpp
    json.cpp
    error.cpp
    string.cpp
)

add_library(
    hogql_parser
    ${PARSER_SOURCES})

target_include_directories(
    hogql_parser
    PRIVATE ${BOOST_INCLUDE_DIR} ${ANTLR_INCLUDE_DIR}
)

target_link_libraries(hogql_parser
    PRIVATE antlr4_static
)

if(EMSCRIPTEN)
    add_executable(hogql_parser_wasm parser_wasm.cpp)
    target_include_directories(hogql_parser_wasm PRIVATE ${BOOST_INCLUDE_DIR} ${ANTLR_INCLUDE_DIR})
    target_link_libraries(hogql_parser_wasm PRIVATE hogql_parser antlr4_static)

    set(CMAKE_EXECUTABLE_SUFFIX ".js")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fwasm-exceptions") # Native WASM exceptions for better exception handling
    set_target_properties(hogql_parser_wasm PROPERTIES
        LINK_FLAGS "\
            -lembind \
            -s WASM=1 \
            -s MODULARIZE=1 \
            -s EXPORT_ES6=1 \
            -s EXPORT_NAME='createHogQLParser' \
            -s ALLOW_MEMORY_GROWTH=1 \
            -s SINGLE_FILE=1 \
        "
    )

    # Install WASM outputs to dist/
    # Usage: cmake --install build_wasm --prefix .
    set(CMAKE_INSTALL_PREFIX ${PROJECT_SOURCE_DIR} CACHE PATH "" FORCE)
    install(TARGETS hogql_parser_wasm RUNTIME DESTINATION dist)
    install(FILES
        ${PROJECT_SOURCE_DIR}/index.d.ts
        ${PROJECT_SOURCE_DIR}/index.cjs
        DESTINATION dist
    )
endif()
