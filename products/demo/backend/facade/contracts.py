"""Public data contracts for the demo product.

######################################################################################
#                                                                                    #
#   DO NOT COPY THIS FILE, OR facade/api.py, INTO A NEW PRODUCT.                     #
#   This product does NOT implement the facade pattern correctly.                    #
#                                                                                    #
#   An empty contracts.py does NOT make a product isolated. is_isolated_product()    #
#   only checks that this file exists, so an empty one still satisfies the           #
#   precondition that eligible_for_isolated_tests builds on. That is a gap in the    #
#   gate, not a license to leave the file empty.                                     #
#                                                                                    #
#   This facade is behavioral: it re-exports `MatrixManager`, `Matrix`,              #
#   `HedgeboxMatrix` and `SpikeGPTMatrix` from logic/. A re-exported class hands     #
#   callers every method (core drives `ensure_account_and_save` from                 #
#   posthog/api/signup.py, which no in-product test pins) while its behavior lives   #
#   outside the contract-check inputs. tach cannot see this: core's import of        #
#   facade.api is legal, and the class travels out through it.                       #
#                                                                                    #
#   So this product does NOT carry backend:contract-check and is NOT isolated -      #
#   it pays the full Django suite. Re-adding the script fails `hogli product:lint`.  #
#                                                                                    #
#   Correct examples: products/visual_review, products/tasks, products/error_tracking#
#                                                                                    #
######################################################################################

The product owns no data model of its own, so there is no product-owned record to define
here yet. This file is the home for any future cross-boundary data record.
"""
