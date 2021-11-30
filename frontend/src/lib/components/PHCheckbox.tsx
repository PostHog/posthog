import React from 'react'

interface Props {
    checked: boolean
    indeterminate?: boolean
    onChange: () => void
    color?: string
    disabled?: boolean
}

export const PHCheckbox = ({
    checked,
    indeterminate,
    color = 'var(--primary)',
    disabled = false,
    ...props
}: Props): JSX.Element => (
    <div
        style={{
            display: 'flex',
            width: '16px',
            height: '16px',
            borderRadius: '3px',
            overflow: 'hidden',
            cursor: disabled ? undefined : 'pointer',
        }}
    >
        <div
            style={{
                display: 'inline-block',
                width: '100%',
                height: '100%',
                background: checked || indeterminate ? color : 'lightgray',
                transition: 'all 150ms',
            }}
            onClick={!disabled ? props.onChange : () => {}}
        >
            <svg
                style={{
                    visibility: checked || indeterminate ? 'visible' : 'hidden',
                    fill: 'none',
                    stroke: 'white',
                    strokeWidth: '2px',
                }}
                viewBox="0 0 24 24"
            >
                {checked ? <polyline points="20 6 9 17 4 12" /> : indeterminate && <polyline points="4 12 20 12" />}
            </svg>
        </div>
    </div>
)
