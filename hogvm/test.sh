#!/bin/bash

cd ..

for file in hogvm/__tests__/*.hog; do
    echo "Testing $file"
    # get the full file path without the .hog extension
    basename="${file%.hog}"

    ./bin/hog $file
    ./bin/hoge --nodejs $basename.hoge > $basename.stdout.nodejs
    ./bin/hoge --python $basename.hoge > $basename.stdout.python
    diff $basename.stdout.nodejs $basename.stdout.python
    if [ $? -eq 0 ]; then
        mv $basename.stdout.nodejs $basename.stdout
        rm $basename.stdout.python
    else
        echo "Test failed"
        rm $basename.stdout.nodejs $basename.stdout.python
    fi
done
