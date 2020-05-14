from behave import *

@given('we are on trends page')
def step_impl(context):
    context.browser.visit('http:/localhost:8000/')
    pass

@when('we implement a test')
def step_impl(context):
    context.TrendsPage.open()
    assert True is not False

@then('behave will test it for us!')
def step_impl(context):
    assert context.failed is False