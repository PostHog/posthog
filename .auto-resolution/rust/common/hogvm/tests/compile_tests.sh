#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR/../../../..
rm rust/common/hogvm/tests/static/test_programs/*.hoge
find rust/common/hogvm/tests/static/test_programs -type f -exec bin/hoge {} \;
cd $SCRIPT_DIR
