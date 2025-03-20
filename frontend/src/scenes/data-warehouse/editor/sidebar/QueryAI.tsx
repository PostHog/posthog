import { LemonInput } from "lib/lemon-ui/LemonInput";
import { IconMagicWand } from "@posthog/icons";
import { useActions } from "kea";
import { multitabEditorLogic } from "../multitabEditorLogic";
import { LemonButton } from "lib/lemon-ui/LemonButton";


export function QueryAI(): JSX.Element {
    const { prompt, setPrompt, draftFromPrompt, draftFromPromptComplete, promptError, promptLoading } = useActions(multitabEditorLogic)

    return <div className="flex flex-col p-2 gap-2">
        <div className="flex gap-2">
            <LemonInput
                className="grow"
                prefix={<IconMagicWand />}
                value={prompt}
                onPressEnter={() => draftFromPrompt()}
                onChange={(value) => setPrompt(value)}
                placeholder={
                    'What do you want to know? How would you like to tweak the query?'
                }
                maxLength={400}
            />
            <LemonButton
                type="primary"
                onClick={() => draftFromPrompt()}
                disabledReason={!prompt
                    ? 'Provide a prompt first'
                    : null
                }
                tooltipPlacement="left"
                loading={promptLoading}
            >
                Think
            </LemonButton>
        </div>
    </div>
}
