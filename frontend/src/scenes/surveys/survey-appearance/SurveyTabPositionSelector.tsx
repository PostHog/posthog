import { SurveyTabPosition } from '~/types'

import { PositionButton } from './PositionButton'

const positions = [SurveyTabPosition.Top, SurveyTabPosition.Left, SurveyTabPosition.Right, SurveyTabPosition.Bottom]

const positionStyles: Record<SurveyTabPosition, React.CSSProperties> = {
    [SurveyTabPosition.Top]: { gridColumn: '2', gridRow: '1' },
    [SurveyTabPosition.Left]: { gridColumn: '1', gridRow: '2' },
    [SurveyTabPosition.Right]: { gridColumn: '3', gridRow: '2' },
    [SurveyTabPosition.Bottom]: { gridColumn: '2', gridRow: '3' },
}

export const SurveyTabPositionSelector = ({
    currentPosition,
    onAppearanceChange,
    disabled,
}: {
    currentPosition?: SurveyTabPosition
    onAppearanceChange: (appearance: { tabPosition: SurveyTabPosition }) => void
    disabled?: boolean
}): JSX.Element => {
    return (
        <div className="grid grid-cols-3 grid-rows-3 gap-1 border border-input bg-surface-primary w-50 p-1 rounded-lg focus-within:border-secondary">
            {positions.map((position) => (
                <div key={position} style={positionStyles[position]}>
                    <PositionButton
                        position={position}
                        isActive={currentPosition === position}
                        onClick={() => onAppearanceChange({ tabPosition: position })}
                        disabled={disabled}
                        alignmentClasses={['items-center', 'justify-center']}
                        ariaLabel={`Tab position: ${position} of screen`}
                    />
                </div>
            ))}
        </div>
    )
}
