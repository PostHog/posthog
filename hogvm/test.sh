#!/bin/bash
set -e
cd typescript
pnpm run build
cd ..

cd ..

rm -f hogvm/__tests__/__snapshots__/*.stdout.nodejs
rm -f hogvm/__tests__/__snapshots__/*.stdout.python

for file in hogvm/__tests__/*.hog; do
    echo "Testing $file"

    # from hogvm/__tests__/*.hog get hogvm/__tests__/__snapshots__/*
    basename="${file%.hog}"
    basename="${basename##*/}"
    basename="hogvm/__tests__/__snapshots__/$basename"

    ./bin/hoge $file $basename.hoge
    ./bin/hog --nodejs $basename.hoge > $basename.stdout.nodejs
    ./bin/hog --python $basename.hoge > $basename.stdout.python

    set +e
    ./bin/hoge $file $basename.js
    node $basename.js > $basename.stdout.compiledjs 2>&1
    set -e

    set +e
    diff $basename.stdout.nodejs $basename.stdout.compiledjs
    if [ $? -eq 0 ]; then
        diff $basename.stdout.nodejs $basename.stdout.python
        if [ $? -eq 0 ]; then
            mv $basename.stdout.nodejs $basename.stdout
            rm $basename.stdout.python
            rm $basename.stdout.compiledjs
        else
            echo "Test failed"
        fi
    else
        echo "Test failed"
    fi
    set -e
done
