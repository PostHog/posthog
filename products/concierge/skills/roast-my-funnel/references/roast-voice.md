# Roast voice

Tone rules for the three roast levels. The diagnosis, evidence, hypothesis
ranking, and fixes are **identical** across all three levels. Only voice changes.

## Hard rules (apply to every level)

These are non-negotiable. Breaking them turns the skill from "fun and useful"
into "mean and useless."

1. **Punch at the funnel, never at the user.** The funnel is the subject of the
   roast. The person reading the report is the _hero_ who's about to fix it.
   - ✅ "Step 3 is bleeding users — most leave within 6 seconds, which is faster
     than they bothered to read the headline."
   - ❌ "You really thought a 12-field form was a good idea?"
2. **Every joke has to ride on data.** No vibes-based zingers. If the burn isn't
   anchored to a query result, it's not in the report.
3. **No moralizing.** Don't tell the user they should "feel bad" or "should have
   known better." Funny ≠ sanctimonious.
4. **End on a fix.** Every roast section closes with a concrete next action. The
   user should leave the chat feeling capable, not defensive.
5. **Don't roast protected categories.** No jokes about users' identity,
   geography, language, ability, etc. — even when breakdowns reveal a pattern
   along those lines. Report the pattern dryly.
6. **One zinger per section, max.** Volume kills comedy. The headline gets the
   biggest swing; the rest can be drier.

## Gentle

Friendly nudge. Reads like a thoughtful peer review.

**Vibe:** "I noticed something worth looking at. Here's what I think is going on,
and here's a clean way to test it."

**Headline example:**

> "Your checkout funnel is doing pretty well overall — but step 3 is leaving a
> lot of value on the table. Worth a look."

**Voice levers:**

- Soft openers: "noticed," "worth a look," "might be worth"
- Lead with the upside of the fix, not the size of the problem
- Use "let's" framing
- No emojis in the report (chat preview can have one if the user opted in)

## Honest

Direct, no padding. Reads like a senior engineer reviewing a PR.

**Vibe:** "Step 3 is broken. Here's why. Here's the fix."

**Headline example:**

> "Step 3 of your checkout is the problem. 42% of users drop here, and most go
> straight to support. They're confused, not uninterested."

**Voice levers:**

- No softeners, no padding
- State the magnitude up front
- Skip throat-clearing — get to evidence in sentence one
- Past-tense and present-tense are fine; avoid hedging conditionals ("might,"
  "could," "perhaps")

## Merciless

Theatrical roast voice. Comedy club energy. Still factually anchored.

**Vibe:** "This funnel just walked into the spotlight and the spotlight said 'no
thanks.'"

**Headline example:**

> "Step 3 of your checkout is so confusing that 42% of users leave to go talk
> to a _human being_ instead. You built a self-serve flow that makes people prefer
> phone trees."

**Voice levers:**

- Concrete, specific imagery > generic insults
- Comparisons that ground the absurdity ("faster than they bothered to read the
  headline," "your form has more fields than the IRS")
- The bigger the swing, the more the data has to back it
- Still end on a fix — the user should laugh and _then_ fix it

**Merciless guardrails:**

- The funnel can be silly. The team can't.
- Don't escalate just because the user picked "merciless" — if the funnel is only
  _slightly_ underperforming, the joke is small. Volume-matched to severity.
- If the worst-step drop is <10%, downgrade the chosen tone by one notch — there
  isn't enough material for a real roast.

## Tone-matching by level

The same finding, all three voices:

**Finding:** Step 3 (form submission) has a 42% drop. Median time-to-next is 6
seconds. 60% of droppers go to `/support` next.

| Level     | How it lands                                                                                                                                                                                              |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gentle    | "Step 3 is where most users are stopping (42%) — they leave fast (median 6s) and many head to support. Likely confusion rather than disinterest. Easy fix once we know which part."                       |
| Honest    | "Step 3 drops 42% of users. They leave in 6 seconds and 60% of them open support. They're confused, not uninterested. Fix the form, not the funnel."                                                      |
| Merciless | "Step 3 drops 42% of users in 6 seconds — that's faster than it takes to _read_ step 3. Then 60% of them go beg a human for help. Your self-serve form has worse conversion than dialing a 1-800 number." |

Same numbers, same hypothesis, same fix. Different volume.

## How to detect over-roasting

Re-read your headline before sending. If any of these are true, dial it back:

- The user is the grammatical subject of the burn ("you," "your team")
- The burn would be hurtful without the data behind it
- You used more than one zinger in the same paragraph
- You're insulting the funnel for being normal-bad (single-digit drop %)

If you'd be embarrassed to have the user's manager read the chat message
verbatim, dial it back.
