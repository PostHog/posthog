import { Progress, Separator, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillPasswordStrength({ score, feedback }: { score: number; feedback?: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="w-20" />}>
                <Progress
                    value={score * 20}
                    variant={score <= 2 ? 'destructive' : score <= 3 ? 'warning' : 'success'}
                    aria-label="Password strength"
                />
            </TooltipTrigger>
            <TooltipContent>
                <div className="flex flex-col gap-1">
                    <span>
                        Your password scores a{' '}
                        <strong>
                            <span>{score}</span>/5
                        </strong>
                    </span>
                    {feedback ? (
                        <>
                            <Separator />
                            <span>{feedback}</span>
                        </>
                    ) : (
                        <span>💪 Nice!</span>
                    )}
                </div>
            </TooltipContent>
        </Tooltip>
    )
}
