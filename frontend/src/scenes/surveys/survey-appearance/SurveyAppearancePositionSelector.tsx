import { ScreenPosition, SurveyPosition } from '~/types'

import { PositionButton } from './PositionButton'

const positionAlignments: Record<ScreenPosition, [string, string]> = {
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

const gridPositions = Object.keys(positionAlignments) as ScreenPosition[]

export function PositionSelector({
    value,
    onChange,
    disabled,
    toolbar,
}: {
    value?: ScreenPosition
    onChange: (position: ScreenPosition) => void
    disabled?: boolean
    toolbar?: boolean
}): JSX.Element {
    return (
        <div
            // toolbar styles are whack - some custom classes and inline styles are required
            // for this to work in toolbar context
            className={
                toolbar
                    ? 'grid grid-cols-3 gap-1 w-36 p-1 rounded-lg'
                    : 'grid grid-cols-3 gap-1 border border-input bg-surface-primary w-36 p-1 rounded-lg focus-within:border-secondary'
            }
            // eslint-disable-next-line react/forbid-dom-props
            style={toolbar ? { border: '1px solid #e5e7eb', backgroundColor: '#f5f5f5' } : undefined}
        >
            {gridPositions.map((position) => (
                <PositionButton
                    key={position}
                    position={position}
                    isActive={value === position}
                    onClick={() => onChange(position)}
                    disabled={disabled}
                    alignmentClasses={positionAlignments[position]}
                    ariaLabel={`Position: ${position}`}
                    toolbar={toolbar}
                />
            ))}
        </div>
    )
}

/** @deprecated Use PositionSelector instead */
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
        <PositionSelector
            value={currentPosition as ScreenPosition}
            onChange={(position) => onAppearanceChange({ position })}
            disabled={disabled}
        />
    )
}
