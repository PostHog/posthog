import { LemonButton, LemonFileInput, LemonInput, LemonSkeleton, lemonToast, Popover, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { useState } from 'react'

import { hogFunctionIconLogic, HogFunctionIconLogicProps } from './hogFunctionIconLogic'

const fileToBase64 = (file?: File): Promise<string> => {
    return new Promise((resolve) => {
        if (!file) {
            return
        }

        const reader = new FileReader()

        reader.onload = (e) => {
            const img = new Image()
            img.onload = () => {
                const canvas = document.createElement('canvas')
                const ctx = canvas.getContext('2d')

                // Set the dimensions at the wanted size.
                const wantedWidth = 128
                const wantedHeight = 128
                canvas.width = wantedWidth
                canvas.height = wantedHeight

                // Resize the image with the canvas method drawImage();
                ctx!.drawImage(img, 0, 0, wantedWidth, wantedHeight)

                const dataURI = canvas.toDataURL()

                resolve(dataURI)
            }
            img.src = e.target?.result as string
        }

        reader.readAsDataURL(file)
    })
}

export function HogFunctionIconEditable({
    size = 'medium',
    ...props
}: HogFunctionIconLogicProps & { size?: 'small' | 'medium' | 'large' }): JSX.Element {
    const { possibleIconsLoading, showPopover, possibleIcons, searchTerm } = useValues(hogFunctionIconLogic(props))
    const { setShowPopover, setSearchTerm } = useActions(hogFunctionIconLogic(props))

    const content = (
        <span className="cursor-pointer" onClick={() => setShowPopover(!showPopover)}>
            <HogFunctionIcon size={size} src={props.src} />
        </span>
    )

    return props.onChange ? (
        <Popover
            showArrow
            visible={showPopover}
            onClickOutside={() => setShowPopover(false)}
            overlay={
                <div className="p-1 w-100 space-y-2">
                    <div className="flex items-center gap-2 justify-between">
                        <h2 className="m-0">Choose an icon</h2>

                        <LemonFileInput
                            multiple={false}
                            accept={'image/*'}
                            showUploadedFiles={false}
                            onChange={(files) => {
                                void fileToBase64(files[0])
                                    .then((dataURI) => {
                                        props.onChange?.(dataURI)
                                    })
                                    .catch(() => {
                                        lemonToast.error('Error uploading image')
                                    })
                            }}
                            callToAction={
                                <LemonButton size="small" type="secondary" icon={<IconUploadFile />}>
                                    Upload image
                                </LemonButton>
                            }
                        />
                    </div>

                    <LemonInput
                        size="small"
                        type="search"
                        placeholder="Search for company logos"
                        fullWidth
                        value={searchTerm ?? ''}
                        onChange={setSearchTerm}
                        prefix={possibleIconsLoading ? <Spinner /> : undefined}
                    />

                    <div className="flex flex-wrap gap-2">
                        {possibleIcons?.map((icon) => (
                            <span
                                key={icon.id}
                                className="cursor-pointer"
                                onClick={() => {
                                    const nonTempUrl = icon.url.replace('&temp=true', '')
                                    props.onChange?.(nonTempUrl)
                                    setShowPopover(false)
                                }}
                            >
                                <HogFunctionIcon src={icon.url} />
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

export function HogFunctionIcon({
    src,
    size = 'medium',
}: {
    src?: string
    size?: 'small' | 'medium' | 'large'
}): JSX.Element {
    const [loaded, setLoaded] = useState(false)

    return (
        <span
            className={clsx('relative flex items-center justify-center', {
                'w-8 h-8 text-2xl': size === 'small',
                'w-10 h-10 text-4xl': size === 'medium',
                'w-12 h-12 text-6xl': size === 'large',
            })}
        >
            {src ? (
                <>
                    <img
                        className={clsx(
                            'w-full h-full rounded overflow-hidden transition-opacity',
                            loaded ? 'opacity-100' : 'opacity-0'
                        )}
                        src={src}
                        onLoad={() => setLoaded(true)}
                    />
                    {!loaded && <LemonSkeleton className="absolute w-full h-full" />}
                </>
            ) : (
                <span>🦔</span>
            )}
        </span>
    )
}
