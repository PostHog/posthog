import React from 'react'

export default function stringWithWBR(text: string, splitAt = 30): JSX.Element {
    const addWBRAfter = [',', '.', '/', '\\']
    const naturalSplit = [' ', '-']

    const returnArray: JSX.Element[] = []
    let final = ''
    let sinceSplit = 0
    let i = 0

    if (text === '') {
        return <i>(empty string)</i>
    }

    text.split('').forEach((letter) => {
        if (addWBRAfter.indexOf(letter) >= 0 || sinceSplit >= splitAt) {
            sinceSplit = 0
            final += letter
            returnArray.push(<span key={i++}>{final}</span>)
            returnArray.push(<wbr key={i++} />)
            final = ''
        } else if (naturalSplit.indexOf(letter) >= 0) {
            sinceSplit = 0
            final += letter
        } else {
            sinceSplit += 1
            final += letter
        }
    })

    if (final) {
        returnArray.push(<span key={i++}>{final}</span>)
    }

    return <span>{returnArray}</span>
}
