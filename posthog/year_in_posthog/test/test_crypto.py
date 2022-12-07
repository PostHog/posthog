from posthog.year_in_posthog.crypto import user_id_decrypt, user_id_encrypt


def test_user_id_can_be_encoded_and_decoded() -> None:
    user_id = "1"

    encrypted = user_id_encrypt(user_id)
    decrypted = user_id_decrypt(encrypted)

    assert decrypted == str(user_id)


def test_two_user_ids_do_not_encode_to_the_same_value() -> None:
    user_id = "2"
    another_user_id = "3"

    encrypted = user_id_encrypt(user_id)
    another_encrypted = user_id_encrypt(another_user_id)

    assert encrypted != another_encrypted

    assert user_id_decrypt(encrypted) == "2"
    assert user_id_decrypt(another_encrypted) == "3"
