import { kea, resetContext } from '../../src'

describe('action types', () => {
  beforeEach(() => {
    resetContext()
  })

  test('action types object is created', () => {
    const logic = kea({
      path: () => ['kea', 'test'],
      actions: {
        updateName: (name) => ({ name }),
        anotherAction: true,
      },
    })

    logic.mount()

    expect(logic.path).toEqual(['kea', 'test'])
    expect(Object.keys(logic.actions).sort()).toEqual(['anotherAction', 'updateName'])

    expect(logic.actionTypes).toEqual({
      anotherAction: logic.actions.anotherAction.toString(),
      updateName: logic.actions.updateName.toString(),
    })
  })
})
