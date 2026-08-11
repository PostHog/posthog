import { Accordion as AccordionPrimitive } from '@base-ui/react/accordion'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import './accordion.css'
import { cn } from './lib/utils'

/**
 * Groups all parts of the accordion.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Accordion](https://base-ui.com/react/components/accordion)
 *
 * @baseui Accordion.Root
 */
function Accordion({ className, ...props }: AccordionPrimitive.Root.Props): React.ReactElement {
    return (
        <AccordionPrimitive.Root
            data-slot="accordion"
            className={cn('quill-accordion flex w-full flex-col', className)}
            {...props}
        />
    )
}

/**
 * Groups an accordion header with the corresponding panel.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Accordion](https://base-ui.com/react/components/accordion)
 *
 * @baseui Accordion.Item
 */
function AccordionItem({ className, ...props }: AccordionPrimitive.Item.Props): React.ReactElement {
    return (
        <AccordionPrimitive.Item
            data-quill
            data-slot="accordion-item"
            className={cn('quill-accordion__item', className)}
            {...props}
        />
    )
}

/**
 * A button that opens and closes the corresponding panel.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Accordion](https://base-ui.com/react/components/accordion)
 *
 * @baseui Accordion.Trigger
 */
function AccordionTrigger({ className, children, ...props }: AccordionPrimitive.Trigger.Props): React.ReactElement {
    return (
        <AccordionPrimitive.Header className="flex">
            <AccordionPrimitive.Trigger
                data-slot="accordion-trigger"
                className={cn(
                    'quill-accordion__trigger group/accordion-trigger relative flex flex-1 items-start justify-between gap-6',
                    className
                )}
                {...props}
            >
                <span>{children}</span>
                <ChevronDownIcon
                    data-slot="accordion-trigger-icon"
                    data-chevron="down"
                    className="pointer-events-none shrink-0"
                />
                <ChevronUpIcon
                    data-slot="accordion-trigger-icon"
                    data-chevron="up"
                    className="pointer-events-none shrink-0"
                />
            </AccordionPrimitive.Trigger>
        </AccordionPrimitive.Header>
    )
}

/**
 * A collapsible panel with the accordion item contents.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Accordion](https://base-ui.com/react/components/accordion)
 *
 * @baseui Accordion.Panel
 */
function AccordionContent({ className, children, ...props }: AccordionPrimitive.Panel.Props): React.ReactElement {
    return (
        <AccordionPrimitive.Panel data-slot="accordion-content" className="quill-accordion__panel" {...props}>
            <div className={cn('quill-accordion__panel-content', className)}>{children}</div>
        </AccordionPrimitive.Panel>
    )
}

export { Accordion, AccordionContent, AccordionItem, AccordionTrigger }
