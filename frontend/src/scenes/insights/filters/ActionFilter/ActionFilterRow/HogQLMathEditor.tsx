import { useState } from 'react'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { QuillHogQLMathPopover } from './QuillHogQLMathPopover'

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
    const quillSurface = useQuillSurface()

    const onChange = (currentValue: string): void => {
        onMathHogQLSelect(index, currentValue)
        setIsVisible(false)
    }

    if (quillSurface) {
        return (
            <div className="flex-auto min-w-0">
                <QuillHogQLMathPopover
                    open={isVisible}
                    onOpenChange={setIsVisible}
                    value={mathHogQL ?? ''}
                    onChange={onChange}
                    data-attr={`math-hogql-select-${index}`}
                />
            </div>
        )
    }

    return (
        <div className="flex-auto min-w-0">
            <LemonDropdown
                visible={isVisible}
                closeOnClickInside={false}
                onClickOutside={() => setIsVisible(false)}
                overlay={
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                        <HogQLEditor value={mathHogQL} onChange={onChange} />
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
