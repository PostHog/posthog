Use the following template to create new expect functions.

This is not a class, it's just a bunch of functions that **do not share state**. All common state should be
stored within `testUtilsContext`.

```ts
import { ActionToDispatch, ExpectFunction } from '~/test/kea-test-utils'

export const toDispatchActions: ExpectFunction<ActionToDispatch[]> = {
    common(logic) {},

    sync(logic, actions) {},

    async async(logic, actions) {},
}
```
