import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldError,
    FieldLabel,
    FieldSet,
    FieldLegend,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { canvasSpaceLabel } from '../canvasTasksApi'
import { newCanvasDialogLogic } from './newCanvasDialogLogic'

/** Picks a space and a template, then creates an empty canvas and opens it. Open it with `openNewCanvasDialog`. */
export function NewCanvasDialog(): JSX.Element {
    const {
        isOpen,
        spaces,
        spacesLoading,
        spacesUnavailable,
        selectedSpaceId,
        templates,
        selectedTemplateId,
        creating,
    } = useValues(newCanvasDialogLogic)
    const { closeNewCanvasDialog, setSelectedSpaceId, setSelectedTemplateId, createCanvas, loadSpaces } =
        useActions(newCanvasDialogLogic)

    const disabledReason = spacesLoading
        ? 'Loading your spaces'
        : !selectedSpaceId
          ? 'Pick a space for the canvas'
          : undefined

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open) => {
                if (!open && !creating) {
                    closeNewCanvasDialog()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>New canvas</DialogTitle>
                    <DialogDescription>
                        A canvas is a small app an agent builds for you, like a dashboard, a form, or a tool.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <form
                        id="new-canvas-form"
                        className="flex flex-col gap-4"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (!disabledReason && !creating) {
                                createCanvas()
                            }
                        }}
                    >
                        <Field>
                            <FieldLabel htmlFor="new-canvas-space">Space</FieldLabel>
                            {spacesUnavailable ? (
                                <div className="flex flex-wrap items-center gap-2">
                                    <FieldError>Your spaces didn't load.</FieldError>
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        loading={spacesLoading}
                                        onClick={() => loadSpaces()}
                                        data-attr="new-canvas-spaces-retry"
                                    >
                                        Try again
                                    </Button>
                                </div>
                            ) : spaces === null ? (
                                <Skeleton className="h-8 w-full" />
                            ) : spaces.length === 0 ? (
                                <FieldError>You don't have a space to put a canvas in yet.</FieldError>
                            ) : (
                                <Select
                                    value={selectedSpaceId ?? ''}
                                    onValueChange={(value) => value && setSelectedSpaceId(String(value))}
                                >
                                    <SelectTrigger id="new-canvas-space" data-attr="new-canvas-space">
                                        <SelectValue>
                                            {(value: string) => {
                                                const space = spaces.find((entry) => entry.id === value)
                                                return space ? canvasSpaceLabel(space) : 'Pick a space'
                                            }}
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {spaces.map((space) => (
                                            <SelectItem key={space.id} value={space.id}>
                                                {canvasSpaceLabel(space)}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            )}
                            <FieldDescription>People who can see the space can open the canvas.</FieldDescription>
                        </Field>
                        <FieldSet>
                            <FieldLegend>Template</FieldLegend>
                            <RadioGroup
                                value={selectedTemplateId}
                                onValueChange={(value) => setSelectedTemplateId(String(value))}
                            >
                                {templates.map((template) => (
                                    <Field key={template.id} orientation="horizontal">
                                        <RadioGroupItem
                                            id={`new-canvas-template-${template.id}`}
                                            value={template.id}
                                            data-attr="new-canvas-template"
                                        />
                                        <FieldContent>
                                            <FieldLabel htmlFor={`new-canvas-template-${template.id}`}>
                                                {template.name}
                                            </FieldLabel>
                                            <FieldDescription>{template.description}</FieldDescription>
                                        </FieldContent>
                                    </Field>
                                ))}
                            </RadioGroup>
                        </FieldSet>
                    </form>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        disabled={creating}
                        onClick={() => closeNewCanvasDialog()}
                        data-attr="new-canvas-cancel"
                    >
                        Cancel
                    </Button>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    type="submit"
                                    form="new-canvas-form"
                                    variant="primary"
                                    loading={creating}
                                    disabled={!!disabledReason}
                                    data-attr="new-canvas-create"
                                />
                            }
                        >
                            Create canvas
                        </TooltipTrigger>
                        {disabledReason && <TooltipContent>{disabledReason}</TooltipContent>}
                    </Tooltip>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
