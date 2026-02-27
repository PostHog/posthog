import { useState } from 'react'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { FormNumberScaleQuestion, FormStarRatingQuestion, FormQuestionType } from 'scenes/surveys/forms/formTypes'

import { QuestionPreviewProps } from '../questionTypeRegistry'

export function RatingPreview({ question, onUpdate }: QuestionPreviewProps): JSX.Element {
    const q = question as FormNumberScaleQuestion | FormStarRatingQuestion
    const numbers = Array.from({ length: q.scale }, (_, i) => i + 1)
    const [hoveredStar, setHoveredStar] = useState(0)
    const isStarRating = q.type === FormQuestionType.StarRating

    return (
        <div className="mt-2 inline-flex flex-col gap-1.5">
            <div className="flex items-center gap-1" onMouseLeave={() => setHoveredStar(0)}>
                {numbers.map((n) =>
                    isStarRating ? (
                        <div
                            key={n}
                            className="cursor-pointer transition-transform hover:scale-110"
                            onMouseEnter={() => setHoveredStar(n)}
                        >
                            {n <= hoveredStar ? (
                                <IconStarFilled className="text-4xl text-warning transition-colors" />
                            ) : (
                                <IconStar className="text-4xl text-muted-3000 transition-colors" />
                            )}
                        </div>
                    ) : (
                        <div
                            key={n}
                            className="w-10 h-10 rounded border border-border bg-bg-3000 flex items-center justify-center text-xs text-muted cursor-default"
                        >
                            {n}
                        </div>
                    )
                )}
            </div>
            {q.type === FormQuestionType.NumberRating && (
                <div className="flex justify-between gap-4">
                    <LemonInput
                        value={q.lowerBoundLabel}
                        onChange={(value) => onUpdate({ ...q, lowerBoundLabel: value })}
                        placeholder="Low label"
                        size="xsmall"
                        className="flex-1 min-w-0"
                    />
                    <LemonInput
                        value={q.upperBoundLabel}
                        onChange={(value) => onUpdate({ ...q, upperBoundLabel: value })}
                        placeholder="High label"
                        size="xsmall"
                        className="flex-1 min-w-0 [&>input]:text-right"
                    />
                </div>
            )}
        </div>
    )
}
