#!/bin/bash
set -e

cd ..

for file in hogvm/__tests__/*.hog; do
    echo "Testing $file"

    # from hogvm/__tests__/*.hog get hogvm/__tests__/snapshots/*
    basename="${file%.hog}"
    basename="${basename##*/}"
    basename="hogvm/__tests__/snapshots/$basename"

    ./bin/hog $file > $basename.hoge
    mv "$file"e $basename.hoge
    ./bin/hoge --nodejs $basename.hoge > $basename.stdout.nodejs
    ./bin/hoge --python $basename.hoge > $basename.stdout.python
    set +e
    diff $basename.stdout.nodejs $basename.stdout.python
    if [ $? -eq 0 ]; then
        mv $basename.stdout.nodejs $basename.stdout
        rm $basename.stdout.python
    else
        echo "Test failed"
        rm $basename.stdout.nodejs $basename.stdout.python
    fi
    set -e
done
