import { kea, resetContext, createActionCreator } from '../../src'

describe('action creators', () => {
  beforeEach(() => {
    resetContext()
  })

  test('action creators work the right way', () => {
    const logic = kea({
      path: () => ['scenes', 'homepage', 'index'],
      actions: () => ({
        updateName: (name) => ({ name }),
        actionWithTrue: true,
        manualAction: createActionCreator('custom_type', (a) => a),
      }),
    })

    logic.mount()

    expect(logic.path).toEqual(['scenes', 'homepage', 'index'])
    expect(Object.keys(logic.actions).sort()).toEqual(['actionWithTrue', 'manualAction', 'updateName'])

    const { actionWithTrue, manualAction, updateName } = logic.actionCreators

    expect(typeof updateName).toBe('function')
    expect(updateName.toString()).toBe('update name (scenes.homepage.index)')
    expect(updateName('newname')).toEqual({ payload: { name: 'newname' }, type: updateName.toString() })

    expect(typeof actionWithTrue).toBe('function')
    expect(actionWithTrue.toString()).toBe('action with true (scenes.homepage.index)')
    expect(actionWithTrue()).toEqual({ payload: { value: true }, type: actionWithTrue.toString() })

    expect(typeof manualAction).toBe('function')
    expect(manualAction.toString()).toBe('custom_type')
    expect(manualAction({ key: 'newname' })).toEqual({ payload: { key: 'newname' }, type: manualAction.toString() })
  })
})
