import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import './collapsible.css'
import { cn } from './lib/utils'

type CollapsibleVariant = 'default' | 'folder'

const CollapsibleVariantContext = React.createContext<CollapsibleVariant>('default')

type CollapsibleProps = CollapsiblePrimitive.Root.Props & {
    variant?: CollapsibleVariant
}

function Collapsible({ variant = 'default', className, ...props }: CollapsibleProps): React.ReactElement {
    return (
        <CollapsibleVariantContext.Provider value={variant}>
            <CollapsiblePrimitive.Root
                data-quill
                data-slot="collapsible"
                data-variant={variant}
                className={cn(
                    'group/collapsible',
                    variant === 'default' && 'quill-collapsible--variant-default',
                    className
                )}
                {...props}
            />
        </CollapsibleVariantContext.Provider>
    )
}

function CollapsibleTrigger({
    children,
    className,
    ...props
}: CollapsiblePrimitive.Trigger.Props): React.ReactElement {
    const variant = React.useContext(CollapsibleVariantContext)
    const chevrons = (
        <>
            <ChevronDownIcon
                data-slot="collapsible-trigger-icon"
                data-chevron="down"
                className="pointer-events-none shrink-0"
            />
            <ChevronUpIcon
                data-slot="collapsible-trigger-icon"
                data-chevron="up"
                className="pointer-events-none shrink-0"
            />
        </>
    )
    return (
        <CollapsiblePrimitive.Trigger
            data-slot="collapsible-trigger"
            data-variant={variant}
            className={cn(
                'quill-collapsible__trigger group/collapsible-trigger flex items-center gap-2 justify-start',
                variant === 'folder' && 'quill-collapsible__trigger--variant-folder',
                className
            )}
            render={<Button size="sm" />}
            {...props}
        >
            {variant === 'folder' && chevrons}
            {children}
            {variant === 'default' && chevrons}
        </CollapsiblePrimitive.Trigger>
    )
}

function CollapsibleContent({ children, className, ...props }: CollapsiblePrimitive.Panel.Props): React.ReactElement {
    const variant = React.useContext(CollapsibleVariantContext)

    return (
        <CollapsiblePrimitive.Panel
            data-slot="collapsible-content"
            className="quill-collapsible__panel"
            {...props}
        >
            <div
                className={cn(
                    'quill-collapsible__panel-content',
                    variant === 'folder' && 'quill-collapsible__panel-content--variant-folder',
                    className
                )}
            >
                {children}
            </div>
        </CollapsiblePrimitive.Panel>
    )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
