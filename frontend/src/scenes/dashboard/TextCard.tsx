import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'

interface TextCardProps extends Resizeable {
    body: string
}

export function TextCard({ body }: TextCardProps): JSX.Element {
    return (
        <div className="TextCard">
            <Textfit mode="single" min={32} max={120}>
                <div className="flex items-center justify-center">{body}</div>
            </Textfit>
        </div>
    )
}
