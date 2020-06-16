import React, { useEffect, useState } from 'react'

export function ChangingText({ lines }) {
    const [line, setLine] = useState(0)

    useEffect(() => {
        const timeout = window.setTimeout(() => {
            setLine((line + 1) % lines.length)
        }, lines[line][1] || 1500)
        return () => window.clearInterval(timeout)
    }, [line])

    return <div>{lines[line][0]}</div>
}
