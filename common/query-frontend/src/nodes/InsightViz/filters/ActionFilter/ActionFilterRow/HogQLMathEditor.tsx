import { useState } from 'react'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

interface HogQLMathEditorDropdownProps {
    mathHogQL: string | null | undefined
    index: number
    onMathHogQLSelect: (index: number, hogql: string) => void
}

export function HogQLMathEditorDropdown({
    mathHogQL,
    index,
    onMathHogQLSelect,
}: HogQLMathEditorDropdownProps): JSX.Element {
    const [isVisible, setIsVisible] = useState(false)

    return (
        <div className="flex-auto min-w-0">
            <LemonDropdown
                visible={isVisible}
                closeOnClickInside={false}
                onClickOutside={() => setIsVisible(false)}
                overlay={
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                        <HogQLEditor
                            value={mathHogQL}
                            onChange={(currentValue) => {
                                onMathHogQLSelect(index, currentValue)
                                setIsVisible(false)
                            }}
                        />
                    </div>
                }
            >
                <LemonButton
                    fullWidth
                    type="secondary"
                    data-attr={`math-hogql-select-${index}`}
                    onClick={() => setIsVisible(!isVisible)}
                >
                    <code>{mathHogQL}</code>
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
