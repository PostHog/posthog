import React from 'react'

export default function stringWithWBR(text: string): JSX.Element {
    const addWBRAfter = [',', '.', '/', '\\']
    const naturalSplit = [' ', '-']

    const returnArray: JSX.Element[] = []
    let final = ''
    let sinceSplit = 0
    let i = 0

    text.split('').forEach((letter) => {
        if (addWBRAfter.indexOf(letter) >= 0 || sinceSplit >= 30) {
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
