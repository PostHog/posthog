import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Link } from 'lib/lemon-ui/Link/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const PERSISTENCE_DOCS_URL =
    'https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps'

interface PersistFlagAcrossAuthenticationProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string
}

/**
 * The "Persist flag across authentication steps" setting for an experiment's new flag. The `test` arm of
 * EXPERIMENT_WIZARD_PERSIST_QUESTION asks it as a yes/no question, to see whether more experiments turn it on.
 * The flag is read here, so only people who see this control count as exposed.
 */
export function PersistFlagAcrossAuthentication({
    checked,
    onChange,
    disabledReason,
}: PersistFlagAcrossAuthenticationProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.EXPERIMENT_WIZARD_PERSIST_QUESTION] === 'test') {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-semibold">
                            Will people see this experiment both before and after they log in?
                        </span>
                        <Link to={PERSISTENCE_DOCS_URL} target="_blank" className="text-sm">
                            Learn more
                        </Link>
                    </div>
                    <LemonSegmentedButton
                        size="small"
                        value={checked ? 'yes' : 'no'}
                        onChange={(value) => onChange(value === 'yes')}
                        disabledReason={disabledReason}
                        options={[
                            { value: 'yes', label: 'Yes', 'data-attr': 'experiment-persist-question-yes' },
                            { value: 'no', label: 'No', 'data-attr': 'experiment-persist-question-no' },
                        ]}
                    />
                </div>
                <div className="text-secondary text-sm">
                    If yes, each person keeps the same variant after they log in. This doesn't work with every setup.
                </div>
            </div>
        )
    }

    return (
        <div>
            <LemonCheckbox
                label="Persist flag across authentication steps"
                onChange={onChange}
                fullWidth
                checked={checked}
                disabledReason={disabledReason}
            />
            <div className="text-secondary text-sm pl-6 mt-2">
                This is only relevant if your feature flag is shown to both logged out AND logged in users. Note that
                this feature is not compatible with all setups,{' '}
                <Link to={PERSISTENCE_DOCS_URL} target="_blank">
                    learn more
                </Link>
            </div>
        </div>
    )
}
