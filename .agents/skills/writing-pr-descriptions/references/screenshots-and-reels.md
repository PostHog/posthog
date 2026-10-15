# Screenshots and reels

A screenshot is the default for every visual change.
A feature reel costs minutes to make, megabytes to load, and seconds to watch.
A screenshot is faster on all three, so a reel must show something a screenshot cannot.

## The test

Write the sentence that tells the reviewer what changed.

- The sentence names one state, or a screenshot makes clear how a person gets there. Take a screenshot.
  "The project menu has an Export item." "Click Export, and a modal opens."
- The sentence names an action and its effect, and a screenshot of the end state hides the action. A reel can carry it.
  "Right-click a session row, and a menu opens." "Select two rows, and a bulk-action bar appears."

Most UI changes fit the first case.
When the user asks for a reel, make it.

## Examples

| Change                                             | Form                          | Why                                                                           |
| -------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------- |
| A new item in an existing menu                     | Screenshot of the open menu   | The item is the change. The reviewer already knows how the menu opens.        |
| A new column, badge, button, or empty state        | Screenshot                    | One state shows all of it                                                     |
| New styles, spacing, or copy                       | Screenshots, before and after | The difference is between two states, not inside a sequence                   |
| A new hover card on an existing element            | Screenshot with the card open | Hover is a familiar trigger, so the content is the change                     |
| A new step in an existing wizard                   | Screenshot of the new step    | The order of the other steps did not change                                   |
| A new loading or skeleton state                    | Screenshot of that state      | The state is the change, not the motion                                       |
| A new right-click menu on an element that had none | Reel, one step                | The trigger is new. A screenshot of a menu does not show where it opens from. |
| Selecting rows shows a new bulk-action bar         | Reel, one or two steps        | A screenshot of the bar does not show what makes it appear                    |
| An undo toast that brings back a deleted row       | Reel, two steps               | The cause and its effect are on screen at different times                     |
| A flow across screens whose order is new           | Reel, two to four steps       | The reviewer must see which action leads to which screen                      |

## What a reel leaves out

A reel shows the new part of a flow, not the path to it.
Each step must show something the PR changed.
When the PR adds a right-click menu to session rows, start on the list and right-click a row.
Do not first open the sidebar and click through to the list.
Do not show the cursor travel to a menu and open it when the menu is not what changed.

Show at most one reel per PR.
When a PR seems to need two, show the main flow and use screenshots for the rest.

A reel replaces the "after" screenshot of the flow, not the "before".
For the "before" of a changed interaction, a screenshot or one line that says how it worked is enough.
A new flow has no before, so say that in one line.
