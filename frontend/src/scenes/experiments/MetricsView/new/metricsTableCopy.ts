export const P_VALUE_SEQUENTIAL_HELP =
    'Sequential testing is enabled. These are always-valid p-values, robust to peeking. They have a slightly different interpretation than ordinary p-values and can often be exactly 1.000 early in the experiment. The result is still statistically significant if the p-value drops below your threshold.'
export const P_VALUE_HELP =
    'The probability of seeing a difference at least this large if the variant had no real effect. The result is significant when the p-value drops below your threshold.'
export const WIN_CHANCE_HELP =
    'Chance to win: the probability that this variant beats the baseline, not the size of the lift.'
export const MULTIPLE_VARIANT_HELP =
    'Some users were exposed to more than one variant. If this percentage is high, there may be an implementation issue causing inconsistent variant assignment.'
