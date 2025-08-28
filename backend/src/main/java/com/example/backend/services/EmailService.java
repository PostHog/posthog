package com.example.backend.services;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import jakarta.mail.internet.MimeMessage;
import java.io.File;
import java.util.List;

@Service
public class EmailService {
    private final JavaMailSender mailSender;

    @Value("${reporting.recipient}")
    private String recipient;

    @Value("${spring.mail.username}")
    private String username;

    @Autowired
    public EmailService(JavaMailSender mailSender) {
        this.mailSender = mailSender;
    }

    @Async
    public void sendReport(String subject, String body, List<File> attachments) throws Exception {
        MimeMessage msg = mailSender.createMimeMessage();
        MimeMessageHelper helper = new MimeMessageHelper(msg, true, "UTF-8");
        helper.setFrom(username);
        helper.setTo(recipient);
        helper.setSubject(subject);
        helper.setText(body, false);

        for (File f : attachments) {
            helper.addAttachment(f.getName(), new FileSystemResource(f));
        }
        mailSender.send(msg);
    }
}
