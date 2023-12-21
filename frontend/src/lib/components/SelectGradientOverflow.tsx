import './SelectGradientOverflow.scss'

// eslint-disable-next-line no-restricted-imports
import { LoadingOutlined } from '@ant-design/icons'
import { LemonTag } from '@posthog/lemon-ui'
import { ConfigProvider, Empty, Select } from 'antd'
import { RefSelectProps, SelectProps } from 'antd/lib/select'
import { useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ANTD_TOOLTIP_PLACEMENTS, toString } from 'lib/utils'
import { ReactElement, RefObject, useEffect, useRef, useState } from 'react'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { CloseButton } from './CloseButton'

interface DropdownGradientRendererProps {
    updateScrollGradient: () => void
    innerRef: RefObject<HTMLDivElement>
    menu: ReactElement
}

function DropdownGradientRenderer({
    updateScrollGradient,
    innerRef,
    menu,
}: DropdownGradientRendererProps): JSX.Element {
    useEffect(() => {
        updateScrollGradient()
    })
    return <div ref={innerRef}>{menu}</div>
}

type CustomTagProps = Parameters<Exclude<SelectProps<any>['tagRender'], undefined>>[0]

export type SelectGradientOverflowProps = SelectProps<any> & {
    delayBeforeAutoOpen?: number
    dropdownMatchSelectWidth?: boolean | number
    placement?: 'bottomLeft' | 'topLeft' // Dropdown placement (undefined = auto). See API at https://ant.design/components/dropdown
    handleBlur?: () => void
    propertyKey?: string
}

/**
 * Ant Design Select extended with a gradient overlay to indicate a scrollable list.
 */
export function SelectGradientOverflow({
    autoFocus = false,
    defaultOpen = false,
    delayBeforeAutoOpen,
    dropdownMatchSelectWidth = true,
    handleBlur = () => {},
    placement,
    propertyKey,
    ...props
}: SelectGradientOverflowProps): JSX.Element {
    const selectRef: React.RefObject<RefSelectProps> | null = useRef(null)
    const containerRef: React.RefObject<HTMLDivElement> = useRef(null)
    const dropdownRef = useRef<HTMLDivElement>(null)
    const [isOpen, setOpen] = useState(false)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    /**
     * Ant Design Tag with custom styling in .scss to match default style
     */
    function CustomTag({ label, onClose, value }: CustomTagProps): JSX.Element {
        // if this component is displaying a list of PropertyFilterValues it needs to format them for display
        if (typeof label === 'string' && propertyKey) {
            label = formatPropertyValueForDisplay(propertyKey, label)
        }
        return (
            <Tooltip title={toString(value)}>
                <LemonTag>
                    <span className="label">{label}</span>
                    <CloseButton onClick={onClose} />
                </LemonTag>
            </Tooltip>
        )
    }

    const updateScrollGradient = (): void => {
        const dropdown = dropdownRef.current
        if (!dropdown) {
            return
        }
        const holder: HTMLDivElement | null = dropdown.querySelector('.rc-virtual-list-holder')
        if (!holder) {
            return
        }
        if (holder.scrollTop > 0) {
            dropdown.classList.add('scrollable-above')
        } else {
            dropdown.classList.remove('scrollable-above')
        }
        if (holder.scrollHeight > holder.scrollTop + holder.offsetHeight) {
            holder.classList.add('scrollable-below')
        } else {
            holder.classList.remove('scrollable-below')
        }
    }

    const onFocus: React.FocusEventHandler<HTMLElement> = (e) => {
        props.onFocus?.(e)
        setTimeout(() => setOpen(true), delayBeforeAutoOpen || 0)
    }

    const onBlur: React.FocusEventHandler<HTMLElement> = (e) => {
        props.onBlur?.(e)
        if (isOpen) {
            setOpen(false)
            handleBlur()
        }
    }

    useEffect(() => {
        if (autoFocus || defaultOpen) {
            selectRef.current?.focus()
        }
    }, [autoFocus, defaultOpen])

    const outsideClickListener = (event: any): void => {
        if (!containerRef.current?.contains(event.target) && !dropdownRef.current?.contains(event.target) && isOpen) {
            selectRef.current?.blur()
        }
    }
    document.addEventListener('click', outsideClickListener)

    return (
        <div ref={containerRef} className="w-full">
            {/*
            This config provider is used to configure the empty data state on the wrapped
            ANT select component
             */}
            <ConfigProvider
                renderEmpty={() => {
                    if (props.loading) {
                        return (
                            <div className="illustration-main text-center">
                                <LoadingOutlined style={{ fontSize: 20 }} />
                                <div>Loading data</div>
                            </div>
                        )
                    } else {
                        return (
                            <div className="illustration-main">
                                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />
                            </div>
                        )
                    }
                }}
            >
                <Select
                    {...props}
                    dropdownAlign={placement ? ANTD_TOOLTIP_PLACEMENTS[placement] : undefined}
                    ref={selectRef}
                    open={isOpen}
                    onFocus={onFocus}
                    onBlur={onBlur}
                    onPopupScroll={() => {
                        updateScrollGradient()
                    }}
                    tagRender={CustomTag}
                    dropdownRender={(menu) => (
                        <DropdownGradientRenderer
                            menu={menu}
                            innerRef={dropdownRef}
                            updateScrollGradient={updateScrollGradient}
                        />
                    )}
                    dropdownMatchSelectWidth={dropdownMatchSelectWidth}
                >
                    {props.children}
                </Select>
            </ConfigProvider>
        </div>
    )
}
