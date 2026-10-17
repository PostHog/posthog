import { Accordion as AccordionPrimitive } from '@base-ui/react/accordion'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import './accordion.css'
import { cn } from './lib/utils'

const Accordion = React.forwardRef<React.ComponentRef<typeof AccordionPrimitive.Root>, AccordionPrimitive.Root.Props>(
    function Accordion({ className, ...props }, ref) {
        return (
            <AccordionPrimitive.Root
                ref={ref}
                data-slot="accordion"
                className={cn('quill-accordion flex w-full flex-col', className)}
                {...props}
            />
        )
    }
)

const AccordionItem = React.forwardRef<
    React.ComponentRef<typeof AccordionPrimitive.Item>,
    AccordionPrimitive.Item.Props
>(function AccordionItem({ className, ...props }, ref) {
    return (
        <AccordionPrimitive.Item
            ref={ref}
            data-quill
            data-slot="accordion-item"
            className={cn('quill-accordion__item', className)}
            {...props}
        />
    )
})

const AccordionTrigger = React.forwardRef<
    React.ComponentRef<typeof AccordionPrimitive.Trigger>,
    AccordionPrimitive.Trigger.Props
>(function AccordionTrigger({ className, children, ...props }, ref) {
    return (
        <AccordionPrimitive.Header className="flex">
            <AccordionPrimitive.Trigger
                ref={ref}
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
})

const AccordionContent = React.forwardRef<
    React.ComponentRef<typeof AccordionPrimitive.Panel>,
    AccordionPrimitive.Panel.Props
>(function AccordionContent({ className, children, ...props }, ref) {
    return (
        <AccordionPrimitive.Panel ref={ref} data-slot="accordion-content" className="quill-accordion__panel" {...props}>
            <div className={cn('quill-accordion__panel-content', className)}>{children}</div>
        </AccordionPrimitive.Panel>
    )
})

export { Accordion, AccordionContent, AccordionItem, AccordionTrigger }
