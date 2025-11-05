import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { SurveyPosition } from '~/types'

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
            {gridPositions.map((position) => {
                const [itemsClass, justifyClass] = positionAlignments[position]

                return (
                    <ButtonPrimitive
                        key={position}
                        size="lg"
                        onClick={() => onAppearanceChange({ position })}
                        active={currentPosition === position}
                        type="button"
                        disabled={disabled}
                        inert={disabled}
                        className={cn('justify-center text-xs w-full p-1', disabled ? 'cursor-not-allowed' : 'group')}
                        aria-label={`Survey position: ${position} of screen`}
                        title={position}
                    >
                        <div className={`flex w-full h-full ${itemsClass} ${justifyClass}`}>
                            <div
                                className={cn(
                                    'size-4 border border-transparent rounded-xs',
                                    currentPosition === position
                                        ? 'bg-accent'
                                        : 'group-hover:bg-accent/40 border-primary'
                                )}
                            />
                        </div>
                    </ButtonPrimitive>
                )
            })}
        </div>
    )
}
