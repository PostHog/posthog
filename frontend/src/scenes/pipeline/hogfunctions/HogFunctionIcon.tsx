import { LemonInput, LemonLabel, LemonSkeleton, Popover, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { hogFunctionIconLogic, HogFunctionIconLogicProps } from './hogFunctionIconLogic'

export function HogFunctionIcon(props: HogFunctionIconLogicProps): JSX.Element {
    const { possibleIconsLoading, showPopover, possibleIcons, searchTerm } = useValues(hogFunctionIconLogic(props))
    const { setShowPopover, setSearchTerm } = useActions(hogFunctionIconLogic(props))

    const content = (
        <span className="relative w-10 h-10 cursor-pointer" onClick={() => setShowPopover(!showPopover)}>
            {possibleIconsLoading ? <Spinner className="absolute -top-1 -right-1" /> : null}
            <img src={props.src} title={props.src} className="w-full h-full rounded overflow-hidden" />
        </span>
    )

    return props.onChange ? (
        <Popover
            showArrow
            visible={showPopover}
            onClickOutside={() => setShowPopover(false)}
            overlay={
                <div className="p-1 w-100">
                    <h2>Choose an icon</h2>

                    <LemonInput
                        size="small"
                        type="search"
                        placeholder="Search for company logos"
                        fullWidth
                        value={searchTerm ?? ''}
                        onChange={setSearchTerm}
                        suffix={possibleIconsLoading ? <Spinner /> : null}
                    />

                    <LemonLabel className="mb-2">Company logos</LemonLabel>

                    <div className="flex flex-wrap gap-2">
                        {possibleIcons?.map((icon) => (
                            <span
                                key={icon.id}
                                className="w-14 h-14 cursor-pointer"
                                onClick={() => {
                                    const nonTempUrl = icon.url.replace('&temp=true', '')
                                    props.onChange?.(nonTempUrl)
                                    setShowPopover(false)
                                }}
                            >
                                <img
                                    src={icon.url}
                                    title={icon.name}
                                    className="w-full h-full rounded overflow-hidden"
                                />
                            </span>
                        )) ??
                            (possibleIconsLoading ? (
                                <LemonSkeleton className="w-14 h-14" repeat={4} />
                            ) : (
                                'No icons found'
                            ))}
                    </div>
                </div>
            }
        >
            {content}
        </Popover>
    ) : (
        content
    )
}
