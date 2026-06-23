---
description: Explain anything at the right altitude using the Feynman technique — plain words, one vivid analogy, then a ladder back up to the precise version so the user can stop at the depth they want. How to pick the analogy and where it breaks. Load when someone asks you to ELI5, 'explain simply', or says they don't follow a concept.
---

# Explain like I'm five

"ELI5" rarely means _talk to me like a literal child_ — it means _strip
the jargon and give me the shape of the thing before the details_. Your
job is to find the altitude where it clicks, then let them climb back up
to precision at their own pace.

## The shape of a good ELI5

1. **One plain sentence, no jargon.** What is it, fundamentally? If you
   can't say it without a term of art, you don't have the core yet.
   > "A database index is like the index at the back of a book — instead
   > of reading every page to find 'mitochondria', you flip to the
   > listing and jump straight there."
2. **One vivid analogy — and only one.** Concrete, everyday, sensory.
   Two analogies muddy it; pick the best and commit.
3. **Show where the analogy breaks.** This is the step that separates a
   _good_ explanation from a cute-but-misleading one. "Where it breaks:
   a book index is fixed when printed; a database index updates every
   time you add a row — which is why writes get a little slower."
4. **The ladder back up.** Offer the next rung, let them choose to take
   it: "Want the real version — B-trees and why lookups are O(log n)?"

## Picking the analogy

- **From their world if you can.** A cook? Compare to a recipe / a
  mise en place. A musician? To a score. Ask or infer one detail about
  who they are and aim the analogy there.
- **Everyday and physical** beats clever. Kitchens, mail, libraries,
  traffic, queues at a counter. People reason well about objects in
  space.
- **Avoid the analogy that needs its own explanation.** If the
  comparison is as obscure as the concept, it isn't helping.

## Calibrate, don't condescend

The failure mode of ELI5 is sounding patronising. Plain ≠ babyish. Don't
say "imagine a teeny tiny computer, sweetie." Say it cleanly and
respect that they're smart — they just don't know _this yet_. Match
their vocabulary as they climb the ladder.

## Check the landing

End with a tiny check, not a lecture: "Does that line up with what you
were picturing, or is there a specific bit that's still fuzzy?" Then
zoom into exactly that bit. The goal is _they can now explain it back_ —
that's the Feynman test, and it's the whole point.
