import { SurveyPosition } from '~/types'

import { PositionButton } from './PositionButton'

const positionAlignments: Record<Exclude<SurveyPosition, SurveyPosition.NextToTrigger>, [string, string]> = {
    [SurveyPosition.TopLeft]: ['items-start', 'justify-start'],
    [SurveyPosition.TopCenter]: ['items-start', 'justify-center'],
    [SurveyPosition.TopRight]: ['items-start', 'justify-end'],
    [SurveyPosition.MiddleLeft]: ['items-center', 'justify-start'],
    [SurveyPosition.MiddleCenter]: ['items-center', 'justify-center'],
    [SurveyPosition.MiddleRight]: ['items-center', 'justify-end'],
    [SurveyPosition.Left]: ['items-end', 'justify-start'],
    [SurveyPosition.Center]: ['items-end', 'justify-center'],
    [SurveyPosition.Right]: ['items-end', 'justify-end'],
}

const gridPositions = Object.keys(positionAlignments) as [keyof typeof positionAlignments]

export const SurveyPositionSelector = ({
    currentPosition,
    onAppearanceChange,
    disabled,
}: {
    currentPosition?: SurveyPosition
    onAppearanceChange: (appearance: { position: SurveyPosition }) => void
    disabled?: boolean
}): JSX.Element => {
    return (
        <div className="grid grid-cols-3 gap-1 border border-input bg-surface-primary w-50 p-1 rounded-lg focus-within:border-secondary">
            {gridPositions.map((position) => (
                <PositionButton
                    key={position}
                    position={position}
                    isActive={currentPosition === position}
                    onClick={() => onAppearanceChange({ position })}
                    disabled={disabled}
                    alignmentClasses={positionAlignments[position]}
                    ariaLabel={`Survey position: ${position} of screen`}
                />
            ))}
        </div>
    )
}
